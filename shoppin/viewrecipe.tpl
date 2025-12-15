<html>
<head>
    <meta http-equiv="refresh" content="1200">
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

a.x {
  opacity: 0.5;
  font-size: 0.8em;
  bottom: 0.3em;
  position: relative;
}

a.edit {
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
    <h1><a href="/">&larr;</a> {{recipe.name}} <a class="edit" href="/edit-recipe/{{recipe.name}}">edit</a></h1>
    % if recipe.description:
    <p style="white-space:pre-wrap">{{recipe.description}}</p>
    % end

    % if recipe.directions:
    <h2>Directions</h2>
    <p style="white-space:pre-wrap">{{recipe.directions}}</p>
    % end

    % if recipe.ingredients:
    <h2>Ingredients</h2>
<table>
    % for item in recipe.ingredients:
  <tr>
     <td>
     % if item.item:
       % if item.item.status.value in [2, 3]:
       &#x2705; 
       % else:
       -
       % end
     % else:
     ?
     % end
     </td>
     <td>{{item.name}}
         &nbsp;&nbsp;{{f"{item.amount:.2g}"}} {{item.amount_unit}}
    % if item.optional:
         <br>&nbsp;&nbsp;<span class="optional">optional</span>
    % end
    % if item.brand:
         <br>&nbsp;&nbsp;Brand: {{item.brand}}
    % end
    % if item.vendor:
         <br>&nbsp;&nbsp;Best Vendor: {{item.vendor}}
    % end
    % end
     </td>
  </tr>
</table>

  </body>
</html>
