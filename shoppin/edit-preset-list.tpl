<html>
<head>
    <meta http-equiv="refresh" content="1200">
    <script src="https://cdn.jsdelivr.net/npm/htmx.org@2.0.5/dist/htmx.min.js" integrity="sha384-t4DxZSyQK+0Uv4jzy5B0QyHyWQD2GFURUmxKMBVww9+e2EJ0ei/vCvv7+79z0fkr" crossorigin="anonymous"></script>

<style>
p{
  width: 50%;
}

a:visited{
  color:blue;
}

a{
text-decoration: none
}

table, th, td {
  border: 1px dotted lightgray;
  border-collapse: collapse;
}
th, td {
  padding: 10px;
}
span.attribution{
  font-style: italic;
  font-size: 13px;
  color: gray;
}

.column {
  float: left;
  width: 50%;
}

.row:after {
  content: "";
  display: table;
  clear: both;
}

span.optional{
  color: gray;
}

a.x{
  opacity: 0.5;
  font-size: 0.8em;
  bottom: 0.3em;
  position: relative;
}

.greendot{
  opacity: 0.5;
  font-size: 0.8em;
}

.alreadyhave{
  text-align: center;
}

</style>
</head>
  <body>
    <h1><a href="/">&larr;</a> <span style="color:red">Editing</span> preset list: "{{preset_list.name}}"</h1>

    <form hx-post="/save-preset-list" hx-trigger="change" hx-swap="none">
    <input type="hidden" name="preset-list" value="{{preset_list.name}}">
    </form>

    <h2>Items</h2>
      <ul>
      % for item_index, item in enumerate(preset_list.items):
        <li>{{item.name}} 
         &nbsp;&nbsp;{{f"{item.amount:.2g}"}} {{item.amount_unit}}
        % if item.optional:
         &nbsp;&nbsp;<span class="optional">optional</span>
        % end
        % if item.brand:
         &nbsp;&nbsp;Brand: {{item.brand}}
        % end
        % if item.vendor:
         &nbsp;&nbsp;Best Vendor: {{item.vendor}}
        % end
         <a class="x" href="/delete-preset-item/{{preset_list.name}}/{{item_index}}"> &#9447;</a>
      % end
      </ul>
      <h3>Add Item</h3>
        <form action="/add-preset-item" method="POST">
          <input type="checkbox" id="optional" name="optional" size="30" method="POST">
          <label for="optional">Optional</label><br>

          <input type="text" id="name" name="item_name" method="POST" size="30" placeholder='Name of item, like "celery"' required>
          <label for="name">Name</label><br>

          <input type="text" id="amount" name="amount" value="1" size="30" method="POST">
          <label for="amount">Amount</label><br>

          <input type="text" id="brand" name="brand" size="30" method="POST">
          <label for="brand">Brand <i>optional</i></label><br>

          <input type="text" id="vendor" name="vendor" size="30" method="POST">
          <label for="vendor">Best Vendor (King Soopers, Safeway, etc) <i>optional</i></label><br>

          <input type="hidden" name="preset_list_name" value="{{preset_list.name}}">
          <input type="submit" value="+ Add Ingredient" hx-boost="true" hx-swap='innerHTML show:no-scroll'><br>
        </form>
  </body>
</html>
